from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import MechExpense, MechExpenseItem
from .forms import ReceiptUploadForm
try:
    from google.cloud import documentai_v1beta3 as documentai
    from google.api_core.exceptions import GoogleAPICallError, PermissionDenied
except Exception:  # Library not installed in local dev
    documentai = None
    class GoogleAPICallError(Exception):
        pass
    class PermissionDenied(Exception):
        pass
import logging

# Configure logging
logger = logging.getLogger(__name__)

@login_required
def upload_receipt(request):
    receipt_data = None  # Initialize receipt_data variable
    error_message = None  # Initialize error_message variable

    if request.method == "POST":
        form = ReceiptUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Process the uploaded file using Document AI
            receipt_file = request.FILES['file']
            receipt_data = process_receipt(receipt_file)  # Call the function to process the receipt

            if receipt_data is None:
                # Set an error message if receipt_data is None
                error_message = 'There was an error processing the receipt. Please try again or check the file format.'

    else:
        form = ReceiptUploadForm()

    # Render the form and display the receipt data (if available) and any errors
    return render(request, 'accounts/receipts/upload_receipt.html', {
        'form': form,
        'receipt_data': receipt_data,
        'error': error_message
    })

def process_receipt(receipt_file):
    if documentai is None:
        logger.error("Google Document AI client not available. Skipping receipt processing.")
        return None

    # Setup for Google Cloud Document AI API
    client = documentai.DocumentProcessorServiceClient()

    # Replace with your project details
    processor_name = "projects/capable-blend-435103-u2/locations/us/processors/a4beb32fc5e44035"

    try:
        # Read the uploaded file content
        receipt_content = receipt_file.read()

        # Create the document object to send to Document AI (PDF or image)
        document = {"content": receipt_content, "mime_type": receipt_file.content_type}

        request = {"name": processor_name, "raw_document": document}

        # Process the receipt with Document AI
        result = client.process_document(request=request)

        # Log the result for debugging purposes
        logger.info(f"Document AI processing result: {result}")

        # Extract fields from the processed receipt
        receipt_fields = result.document.fields

        if not receipt_fields:
            logger.error("No fields found in the receipt")
            return None

        # Extract vendor, date, receipt number, and line items
        extracted_data = {
            'vendor': receipt_fields.get('vendor_name', {}).get('text', 'Unknown Vendor'),
            'date': receipt_fields.get('date', {}).get('text', None),
            'receipt_no': receipt_fields.get('receipt_no', {}).get('text', 'Unknown Receipt No'),
            'items': []
        }

        # Process line items from the receipt, if present
        line_items = receipt_fields.get('line_items', [])
        for item in line_items:
            extracted_data['items'].append({
                'part_no': item.fields.get('part_no', {}).get('text', 'N/A'),
                'description': item.fields.get('description', {}).get('text', 'N/A'),
                'qty': float(item.fields.get('qty', {}).get('text', 0)),
                'price': float(item.fields.get('price', {}).get('text', 0))
            })

        return extracted_data

    except PermissionDenied as e:
        logger.error(f"Permission denied: {e}")
        return None

    except GoogleAPICallError as e:
        logger.error(f"Error while processing receipt with Document AI: {e}")
        return None
