from django.utils.deprecation import MiddlewareMixin


class AllowIframeFromPortfolioMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        # Allow embedding in iframe from portfolio site
        response['X-Frame-Options'] = 'ALLOWALL'
        response['Content-Security-Policy'] = "frame-ancestors 'self' https://www.madebyparm.com"
        return response
