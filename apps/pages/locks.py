from contextlib import contextmanager

from django.db import connection, transaction


@contextmanager
def project_advisory_lock(project_id, namespace='pages'):
    lock_name = f'{namespace}:{project_id}'
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s))', [lock_name])
            acquired = cursor.fetchone()[0]

        if not acquired:
            yield False
            return

        yield True
