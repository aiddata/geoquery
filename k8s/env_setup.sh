
source <(kubectl completion bash) # set up autocomplete in bash into the current shell, bash-completion package should be installed first.
echo "source <(kubectl completion bash)" >> ~/.bashrc # add autocomplete permanently to your bash shell.

alias k="kubectl"
alias kd="kubectl describe"
alias kg="kubectl get"
alias kga="kubectl get all"

echo 'alias k="kubectl"' >> ~/.bashrc
echo 'alias kd="kubectl describe"' >> ~/.bashrc
echo 'alias kg="kubectl get"' >> ~/.bashrc
echo 'alias kga="kubectl get all"' >> ~/.bashrc

complete -o default -F __start_kubectl k
