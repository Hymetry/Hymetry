from django.core.management.base import BaseCommand
import time

from apps.tracker.models import Session
from apps.tracker.bubble_cache_manager import BubbleCacheManager


class Command(BaseCommand):
    help = 'Calculate and cache bubble sizes for all projects using optimized algorithm'

    def add_arguments(self, parser):
        parser.add_argument(
            '--project-id',
            type=int,
            help='Calculate cache for specific project ID only'
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=7,
            help='Number of days back to process (default: 7)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recalculate even if cache exists'
        )

    def handle(self, *args, **options):
        start_time = time.time()
        self.stdout.write("🚀 Starting optimized bubble cache calculation...")
        
        project_id = options.get('project_id')
        days_back = options.get('days_back')
        force = options.get('force')
        
        # Get projects to process
        if project_id:
            projects = Session.objects.filter(visitor__project_id=project_id).values_list('visitor__project', flat=True).distinct()
        else:
            projects = Session.objects.values_list('visitor__project', flat=True).distinct()
        
        if not projects:
            self.stdout.write(self.style.WARNING("No projects found with sessions"))
            return
        
        self.stdout.write(f"📊 Processing {len(projects)} projects...")
        
        total_cache_entries = 0
        total_sessions = 0
        
        for project_id in projects:
            self.stdout.write(f"🔄 Processing project {project_id}...")
            
            # Use BubbleCacheManager to cache bubbles for this project
            result = BubbleCacheManager.cache_bubbles_for_project(
                project_id=project_id,
                days_back=days_back,
                force=force
            )
            
            if not result['success']:
                self.stdout.write(f"  ⚠️  {result['error']}")
                continue
            
            if result.get('skipped'):
                self.stdout.write(
                    f"  ✅ Cache exists for project {project_id} ({result['cache_entries']} entries)"
                )
            else:
                timing = result.get('timing', {})
                cache_stats = f"created: {result.get('cache_created', 0)}, updated: {result.get('cache_updated', 0)}"
                self.stdout.write(
                    f"  ✅ Project {project_id}: {result['cache_entries']} entries modified/added ({cache_stats}) in {result['time']:.3f}s\n"
                    f"     📏 Normalization factor: {result['normalization_factor']:.4f}\n"
                    f"     📊 Sessions: {result['sessions']}, Events: {result['events']}\n"
                    f"     ⏱️  Events query: {timing.get('events_query', 0):.3f}s, "
                    f"Cache creation: {timing.get('cache_creation', 0):.3f}s"
                )
            
            total_cache_entries += result['cache_entries']
            total_sessions += result['sessions']
        
        total_time = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"🎉 Cache calculation completed!\n"
                f"📊 Total sessions: {total_sessions}\n"
                f"💾 Total entries modified/added: {total_cache_entries}\n"
                f"⏱️  Total time: {total_time:.3f}s"
            )
        ) 