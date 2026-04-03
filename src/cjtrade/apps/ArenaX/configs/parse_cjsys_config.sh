
if [ ! -f $1 ]; then
    echo "file $1 not found!"
    exit 1
fi

function print_env_var_as_python_list() {
    printf %s 'keys = ['
    while read -r line; do
       printf "\'%s\', " "$line"
    done < <(cat $1 | grep AX_ | awk '{print $1}')
    printf %s ']'
}

function print_env_var() {
    while read -r line; do
        echo "$line"
    done < <(cat $1 | grep AX_ | awk '{print $1}')
}

# print_env_var $1
print_env_var_as_python_list $1
