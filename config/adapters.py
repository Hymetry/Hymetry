from allauth.account.adapter import DefaultAccountAdapter


class MyAccountAdapter(DefaultAccountAdapter):
    def populate_username(self, request, user):
        # Force username to be the full email
        user.username = user.email
