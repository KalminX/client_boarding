from django.apps import AppConfig

class WorkflowEngineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'workflow_engine'

    def ready(self):
        # Import handlers to ensure they are registered with the JobRegistry
        import workflow_engine.handlers  # noqa
