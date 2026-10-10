from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from .models import Job, JobStatus
from .dispatcher import retry_job, cancel_job, enqueue_job
from .worker import JobWorker

@login_required
def job_monitor_view(request):
    jobs = Job.objects.all().order_by('-created_at')
    
    status_filter = request.GET.get('status')
    if status_filter and status_filter != 'all':
        jobs = jobs.filter(status=status_filter)

    type_filter = request.GET.get('type')
    if type_filter:
        jobs = jobs.filter(job_type=type_filter)

    search_query = request.GET.get('q')
    if search_query:
        jobs = jobs.filter(id__icontains=search_query) | jobs.filter(correlation_id__icontains=search_query)

    paginator = Paginator(jobs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Stats counts
    counts = {
        'all': Job.objects.count(),
        'pending': Job.objects.filter(status=JobStatus.PENDING).count(),
        'running': Job.objects.filter(status=JobStatus.RUNNING).count(),
        'retrying': Job.objects.filter(status=JobStatus.RETRYING).count(),
        'succeeded': Job.objects.filter(status=JobStatus.SUCCEEDED).count(),
        'failed': Job.objects.filter(status=JobStatus.FAILED).count(),
        'cancelled': Job.objects.filter(status=JobStatus.CANCELLED).count(),
    }

    return render(request, 'workflow_engine/job_monitor.html', {
        'page_obj': page_obj,
        'counts': counts,
        'status_filter': status_filter or 'all',
        'type_filter': type_filter or '',
        'search_query': search_query or '',
    })


@login_required
def retry_job_view(request, job_id):
    if request.method == 'POST':
        job = retry_job(job_id)
        if job:
            messages.success(request, f"Job {job.id} ({job.job_type}) has been requeued for immediate execution.")
        else:
            messages.error(request, f"Job {job_id} could not be found or retried.")
    return redirect(request.META.get('HTTP_REFERER', 'job_monitor'))


@login_required
def cancel_job_view(request, job_id):
    if request.method == 'POST':
        job = cancel_job(job_id)
        if job:
            messages.info(request, f"Job {job.id} has been cancelled.")
        else:
            messages.error(request, f"Job {job_id} could not be found.")
    return redirect(request.META.get('HTTP_REFERER', 'job_monitor'))


@login_required
def run_worker_once_view(request):
    """
    Triggers the worker synchronously for all currently due jobs and redirects back.
    Enables instant demonstration in development without needing a separate terminal.
    """
    if request.method == 'POST':
        worker = JobWorker(poll_interval=0.1)
        # Recover abandoned first
        recovered = worker.recover_abandoned_jobs()
        # Run until all due jobs processed
        worker.run(once=True)
        messages.success(request, f"Worker executed successfully! Any due jobs were processed.")
    return redirect(request.META.get('HTTP_REFERER', 'job_monitor'))
