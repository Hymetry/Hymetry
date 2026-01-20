def project_context(request):
    """
    Context processor to provide selected_project and user_projects to all templates.
    """
    context = {}
    
    if request.user.is_authenticated:
        # Get user's projects with details
        user_projects = request.user.projectmembership_set.select_related('project').all()
        context['user_projects'] = user_projects
        
        # Get selected project from query parameters or session ID
        selected_project = None
        
        # First try to get project from query parameters
        try:
            project_id = int(request.GET.get('project'))
            # Verify user has access to this project
            if project_id in [membership.project.id for membership in user_projects]:
                selected_project = next((membership.project for membership in user_projects 
                                       if membership.project.id == project_id), None)
        except (TypeError, ValueError):
            pass
        
        # If no project from query params, try to get from URL path
        if not selected_project:
            from apps.tracker.models import Session
            try:
                # Extract project_id or session_id from URL path
                path_parts = request.path.strip('/').split('/')
                
                # Check for new URL structure: projects/<project_id>/ or projects/<project_id>/recordings/
                if len(path_parts) >= 2 and path_parts[0] == 'projects':
                    project_id = int(path_parts[1])
                    # Verify user has access to this project
                    if project_id in [membership.project.id for membership in user_projects]:
                        selected_project = next((membership.project for membership in user_projects 
                                               if membership.project.id == project_id), None)
                
                # Check for old tracker/recordings/<project_id>/ path (backward compatibility)
                elif len(path_parts) >= 3 and path_parts[0] == 'tracker' and path_parts[1] == 'recordings':
                    project_id = int(path_parts[2])
                    # Verify user has access to this project
                    if project_id in [membership.project.id for membership in user_projects]:
                        selected_project = next((membership.project for membership in user_projects 
                                               if membership.project.id == project_id), None)
                
                # Check for tracker/recording/<session_id>/ path
                elif len(path_parts) >= 3 and path_parts[0] == 'tracker' and path_parts[1] == 'recording':
                    session_id = path_parts[2]
                    print(f"DEBUG: Found session_id in URL: {session_id}")
                    print(f"DEBUG: Path parts: {path_parts}")
                    # Get session and its project
                    try:
                        session = Session.objects.get(
                            session_id=session_id,
                            visitor__project__in=[membership.project.id for membership in user_projects]
                        )
                        selected_project = session.visitor.project
                        print(f"DEBUG: Found session project: {selected_project.id}")
                    except Session.DoesNotExist:
                        print(f"DEBUG: Session not found for session_id: {session_id}")
                        print(f"DEBUG: Available project IDs: {[membership.project.id for membership in user_projects]}")
                        # Try without project filter to see if session exists
                        try:
                            session = Session.objects.get(session_id=session_id)
                            print(f"DEBUG: Session exists but project {session.visitor.project.id} not in user projects")
                        except Session.DoesNotExist:
                            print(f"DEBUG: Session does not exist at all")
            except (Session.DoesNotExist, ValueError, IndexError):
                pass
        
        context['selected_project'] = selected_project
    
    return context 