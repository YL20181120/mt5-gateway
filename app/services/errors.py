class ServiceError(Exception):
    """An expected domain failure with a transport-independent response."""

    def __init__(self, message, status=500, error_type="service_error", details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.details = details
