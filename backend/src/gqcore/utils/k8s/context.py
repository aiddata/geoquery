def get_current_namespace() -> str:
    return open("/var/run/secrets/kubernetes.io/serviceaccount/namespace").read()
