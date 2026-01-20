from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Note
from .forms import NoteForm
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string

# Add a new note
@login_required
def add_note(request):
    if request.method == 'POST':
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.user = request.user  # Link note to the current user
            note.save()
            return redirect('accounts:home')  # Redirect to home after saving the note
    return redirect('accounts:home')

# Edit an existing note
@login_required
def edit_note(request, note_id):
    note = get_object_or_404(Note, id=note_id, user=request.user)  # Ensure note belongs to the user
    if request.method == 'POST':
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            return redirect('accounts:home')
    else:
        form = NoteForm(instance=note)

    # Pass both the form and the note object to the template
    return render(request, 'notes/note_edit.html', {'form': form, 'note': note})


# Delete a note
@login_required
def delete_note(request, note_id):
    note = get_object_or_404(Note, id=note_id, user=request.user)
    if request.method == 'POST':
        note.delete()
        return redirect('accounts:home')
    return render(request, 'notes/note_confirm_delete.html', {'note': note})

# Pin or unpin a note
@login_required
def pin_note(request, note_id):
    note = get_object_or_404(Note, id=note_id, user=request.user)
    note.pinned = not note.pinned  # Toggle pinned status
    note.save()
    return redirect('accounts:home')

# View all notes (expanded view)
@login_required
def expand_notes(request):
    notes = Note.objects.filter(user=request.user)

    # Filter by date
    selected_date = request.GET.get('date')
    if selected_date:
        notes = notes.filter(created_at__date=selected_date)

    # Sorting logic if needed
    sort_by = request.GET.get('sort')
    if sort_by:
        notes = notes.order_by(sort_by)

    return render(request, 'notes/note_expand.html', {'notes': notes})

@login_required
def notes_sort(request):
    sort_by = request.GET.get('sort', 'created_at')  # Default sort by created_at
    order = request.GET.get('order', 'asc')  # Ascending by default

    if order == 'desc':
        sort_by = '-' + sort_by  # Prepend dash for descending order

    notes = Note.objects.filter(user=request.user).order_by(sort_by)
    return render(request, 'notes/note_expand.html', {'notes': notes})


# Search notes
@login_required
def live_search(request):
    query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'created_at')  # Default sorting by created_at
    order = request.GET.get('order', 'asc')  # Default sorting order is ascending

    # Adjust the ordering based on ascending or descending
    if order == 'desc':
        sort_by = f'-{sort_by}'

    # Filter the notes based on the search query and user
    if query:
        notes = Note.objects.filter(
            Q(user=request.user) &
            (Q(content__icontains=query) | Q(title__icontains=query))
        ).order_by(sort_by, '-pinned', '-created_at')
    else:
        notes = Note.objects.filter(user=request.user).order_by(sort_by, '-pinned', '-created_at')

    # Render the updated list of notes as HTML and return as JSON
    html = render_to_string('notes/note_list.html', {'notes': notes})
    return JsonResponse({'html': html})
