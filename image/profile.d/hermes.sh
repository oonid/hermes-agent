export HERMES_HOME=/root/.hermes/profiles/android
case ":$PATH:" in
    *":/root/.local/bin:"*) ;;
    *) export PATH="/root/.local/bin:$PATH" ;;
esac
