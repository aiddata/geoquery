
source <(kubectl completion bash) # set up autocomplete in bash into the current shell, bash-completion package should be installed first.
echo "source <(kubectl completion bash)" >> ~/.bashrc # add autocomplete permanently to your bash shell.

alias k="kubectl"
alias kd="kubectl describe"
alias kg="kubectl get"
alias kga="kubectl get all"
complete -o default -F __start_kubectl k
