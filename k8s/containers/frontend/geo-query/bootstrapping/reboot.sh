#!/bin/bash


if [[ $USER == "vagrant" ]] || [[ $USER == "ubuntu" ]]; then

    echo "Building vagrant environment"
    web_dir=/vagrant/www

elif [[ $USER == "aiddata" ]]; then

    echo "Building server environment"
    web_dir=/var/www/query

else
    echo Must be run as \"aiddata\" user \(do not run as root\) on prod/dev server or using vagrant for local development
    exit 1
fi


cd ${web_dir}

sudo service nodeserver start

grunt build

