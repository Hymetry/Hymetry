from celery import shared_task

from .models import Project


@shared_task
def send_invitation_email(unique_emails, project_id, invited_by_id):
    """
    Celery task to send invitation email using InvitationHandler
    
    Args:
        unique_emails (list): Email address list to send invitation to
        project_id (int): ID of the project
        invited_by_id (int): ID of the user sending the invitation
    """
    # Local import to avoid circular import
    from apps.projects.invitation_handler import InvitationHandler

    project = Project.objects.get(pk=project_id)
    invited_by = project.owner  # We'll use project owner for now

    # Use InvitationHandler to create invitation
    handler = InvitationHandler(project, invited_by)
    for email in unique_emails:
        try:
            result = handler.create_invitation(email)
            if result['success']:
                print(f"Successfully sent invitation to {email}")
            else:
                print(f"Failed to send invitation to {email}: {result['reason']}")

        except Exception as e:
            # Log the error (you might want to use Django's logging here)
            print(f"Failed to send invitation email to {email}: {str(e)}")
