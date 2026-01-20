from django.shortcuts import redirect
from apps.projects.models import Invitation, ProjectMembership

class InvitationRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        token = request.COOKIES.get('pending_invitation_token')
        if token and request.user.is_authenticated:
            try:
                invitation = Invitation.objects.get(token=token, active=False)
                if invitation.is_expired():
                    response.delete_cookie('pending_invitation_token')
                    return response
                if request.user.email.lower() == invitation.email.lower():
                    # Auto-verify the email address since they confirmed the invitation
                    from allauth.account.models import EmailAddress
                    email_address, created = EmailAddress.objects.get_or_create(
                        user=request.user,
                        email=request.user.email,
                        defaults={'verified': True, 'primary': True}
                    )
                    if not created:
                        # If email address already exists, mark it as verified
                        email_address.verified = True
                        email_address.primary = True
                        email_address.save()

                    already_member = ProjectMembership.objects.filter(user=request.user, project=invitation.project).exists()
                    already_active = Invitation.objects.filter(project=invitation.project, email=invitation.email, active=True).exists()
                    if not already_member:
                        ProjectMembership.objects.get_or_create(
                            user=request.user, project=invitation.project, defaults={'is_owner': False}
                        )
                    # Mark this invitation as accepted and clean up other pending invitations
                    invitation.active = True
                    invitation.save()
                    # Clean up other pending invitations for the same email
                    Invitation.objects.filter(
                        project=invitation.project, 
                        email=invitation.email, 
                        active=False
                    ).exclude(id=invitation.id).delete()
                    response.delete_cookie('pending_invitation_token')
                    return redirect('projects:project_list')
                else:
                    # Mark as failed if wrong user
                    invitation.failed = True
                    invitation.save()
                    response.delete_cookie('pending_invitation_token')
                    return redirect('projects:project_list')
            except Invitation.DoesNotExist:
                response.delete_cookie('pending_invitation_token')
                return response
        return response 