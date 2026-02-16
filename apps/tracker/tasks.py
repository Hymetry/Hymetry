import json
import subprocess
import openai
from celery import shared_task
from openai import OpenAIError
from django.conf import settings
from django.db import models

from config.utils import get_django_settings_module
from apps.projects.models import ChatGptKey
from apps.tracker.models import Page, Session, TitlePrompt, OpenAIModel, ProjectNormalizationFactor
from apps.tracker.session_visualizer import SessionVisualizer


@shared_task
def generate_clean_title(project_id, page_id):
    try:
        print("Task generate_clean_title started")
        page = Page.objects.get(id=page_id)
        prompt = TitlePrompt.objects.filter(is_active=True).first()

        if not prompt:
            raise Exception("No active prompt found")

        full_prompt = prompt.prompt_text.replace("{{ORIGINAL_TITLE}}", page.original_title)
        full_prompt = full_prompt.replace("{{PAGE_URL}}", page.url)
        print(full_prompt)
        # Use the current OpenAI API format
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY_PROVIDER(project_id))
        openai_model = OpenAIModel.objects.filter(is_active=True).first()
        openai_model_name = 'gpt-4o' if openai_model is None else openai_model.name

        response = client.chat.completions.create(
            model=openai_model_name,
            messages=[{"role": "user", "content": full_prompt}],
            # temperature=0.3,
        )
        title = response.choices[0].message.content.strip()
        title_dict = json.loads(title)
        page.title = title_dict.get("title", page.original_title)
        page.save()
        output = f"Task generate_clean_title finished: {page.original_title} - {page.title}"
        print(output)
        ChatGptKey.objects.update_check_fields(project_id, True)
        return output
    except Page.DoesNotExist:
        return f"Page {page_id} not found"
    except OpenAIError as e:
        ChatGptKey.objects.update_check_fields(project_id, False)
        return f"OpenAI error: {e}"
    except Exception as e:
        return f"Unhandled error: {e}"


@shared_task
def process_pages_with_empty_titles():
    """
    Periodic task that finds pages with empty titles and generates clean titles for them.
    This task should be scheduled to run periodically (e.g., every hour or daily).
    """
    try:
        print("Task process_pages_with_empty_titles started")
        
        # Find pages that have empty _title field but have an original_title
        pages_with_empty_titles = Page.objects.filter(
            models.Q(_title__isnull=True) | models.Q(_title__exact="")
        ).exclude(
            original_title__isnull=True
        ).exclude(
            original_title__exact=""
        )
        
        print(f"Found {pages_with_empty_titles.count()} pages with empty titles")
        
        processed_count = 0
        error_count = 0
        
        for page in pages_with_empty_titles:
            try:
                # Page has no project FK; get project_id from a session that has this page (Event -> Session -> Visitor -> project)
                project_id = Session.objects.filter(events__page=page).values_list('visitor__project_id', flat=True).first()
                result = generate_clean_title.delay(project_id, page.id)
                processed_count += 1
                print(f"Queued generate_clean_title task for page {page.id}: {page.original_title}")
            except Exception as e:
                error_count += 1
                print(f"Error queuing task for page {page.id}: {e}")
        
        print(f"Task process_pages_with_empty_titles finished: {processed_count} tasks queued, {error_count} errors")
        return {
            "processed_count": processed_count,
            "error_count": error_count,
            "total_pages_found": pages_with_empty_titles.count()
        }
        
    except Exception as e:
        print(f"Error in process_pages_with_empty_titles task: {e}")
        return f"Unhandled error: {e}"


@shared_task
def calculate_bubble_cache():
    """
    Calculate and cache bubble sizes for all pages in all sessions.
    Delegates the work to SessionVisualizer class.
    """
    try:
        print("Task calculate_bubble_cache started")
        result = SessionVisualizer.calculate_and_cache_bubbles_for_all_pages()
        print("Task calculate_bubble_cache finished")
        return result
    except Exception as e:
        print(f"Error in calculate_bubble_cache task: {e}")
        return f"Unhandled error: {e}"


@shared_task
def calculate_project_normalization_factors():
    """
    Calculate normalization factors for all projects and store them in the database.
    This task runs the heavy normalization calculation that queries last week's data.
    """
    try:
        print("Task calculate_project_normalization_factors started")
        
        # Get all unique projects that have events
        from apps.tracker.models import Session
        projects = Session.objects.values_list('visitor__project', flat=True).distinct()
        
        results = {}
        
        for project_id in projects:
            try:
                # Calculate normalization factor for this project
                k = SessionVisualizer.calculate_normalization_factor(project_id)
                
                # Store the result in the database (update existing or create new)
                factor_obj, created = ProjectNormalizationFactor.objects.update_or_create(
                    project_id=project_id,
                    defaults={'factor': k}
                )
                
                results[project_id] = k
                action = "Created" if created else "Updated"
                print(f"{action} normalization factor for project {project_id}: {k}")
                
            except Exception as e:
                print(f"Error calculating normalization factor for project {project_id}: {e}")
                results[project_id] = 1000  # Default value
        
        print(f"Task calculate_project_normalization_factors finished. Processed {len(results)} projects.")
        return results
        
    except Exception as e:
        print(f"Error in calculate_project_normalization_factors task: {e}")
        return f"Unhandled error: {e}"


def get_project_normalization_factor(project_id):
    """
    Get the most recent normalization factor for a project from the database.
    If not found, return a default value of 1.
    """
    try:
        factor_obj = ProjectNormalizationFactor.objects.filter(
            project_id=project_id
        ).first()
        return factor_obj.factor if factor_obj else 1000.0
    except Exception:
        return 1000.0


@shared_task
def run_calculate_bubble_cache():
    result = subprocess.run(
        ["python", "manage.py", "calculate_bubble_cache", f"--settings={get_django_settings_module()}"],
        capture_output=True,
        text=True,
    )
    # result.stdout contains standard output
    # result.stderr contains error output
    if result.returncode == 0:
        return result.stdout  # return the command output for Flower
    else:
        # You can raise an exception or return error info
        return f"Error {result.returncode}: {result.stderr}"