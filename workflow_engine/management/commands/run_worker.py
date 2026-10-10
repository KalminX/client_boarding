import logging
from django.core.management.base import BaseCommand
from workflow_engine.worker import JobWorker

logger = logging.getLogger('workflow_engine')

class Command(BaseCommand):
    help = "Starts the database-backed background worker to process scheduled and queued jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            '--worker-id',
            type=str,
            default=None,
            help="Unique identifier for this worker instance (default: auto-generated)"
        )
        parser.add_argument(
            '--interval',
            type=float,
            default=None,
            help="Polling interval in seconds when queue is idle (default from settings)"
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=None,
            help="Batch size for candidate job discovery"
        )
        parser.add_argument(
            '--lease-duration',
            type=int,
            default=None,
            help="Lease duration in seconds for running jobs"
        )
        parser.add_argument(
            '--max-jobs',
            type=int,
            default=None,
            help="Maximum number of jobs to process before stopping (useful for testing or batch runs)"
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help="Process all currently due jobs once and exit immediately"
        )

    def handle(self, *args, **options):
        # Configure logging to stdout if running as management command
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'
        )
        
        self.stdout.write(self.style.SUCCESS("Starting Custom Database-Backed Job Worker..."))
        
        worker = JobWorker(
            worker_id=options['worker_id'],
            poll_interval=options['interval'],
            batch_size=options['batch_size'],
            lease_duration_seconds=options['lease_duration'],
        )

        self.stdout.write(f"Worker initialized: ID={worker.worker_id}, Poll Interval={worker.poll_interval}s, Lease={worker.lease_duration}s")
        
        try:
            worker.run(max_jobs=options['max_jobs'], once=options['once'])
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Worker interrupted by keyboard."))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Worker crashed with error: {exc}"))
            raise
