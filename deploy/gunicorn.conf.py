bind = '127.0.0.1:8010'
workers = 2
timeout = 120
accesslog = '-'
# Exclude query strings (OAuth authorization codes) from access logs.
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
errorlog = '-'
umask = 0o077
