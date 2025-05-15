# updated for ubuntu 18.04

ubuntu_version=$(lsb_release -sr)
echo Running Ubuntu ${ubuntu_version}

boot_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# boot_dir=/opt/aiddata/geo-query/bootstrapping

root_dir="$( dirname ${boot_dir} )"


if [[ $USER == "vagrant" ]]; then

    echo "Building vagrant environment"
    web_dir=/vagrant/www

elif [[ $USER == "aiddata" ]]; then

    echo "Building server environment"
    web_dir=/var/www/query

else
    echo Must be run as \"aiddata\" user \(do not run as root\) on prod/dev server or using vagrant for local development
    exit 1
fi


sudo apt-get update

# RUN OUR INSTALLS:

# TOOLS
  # unzip
  # curl
  # vim
  # git

# SERVER UTILS
  # nginx - for internal app routing with port forwarding
  # python
  # g++
  # make

# WEBSERVER UTILS
  # nodejs
  # monit - for restarting webserver after crashes, and reporting


sudo apt install -y unzip curl vim git nginx software-properties-common python g++ make nano monit

# https://github.com/nodesource/distributions#debinstall
curl -sL https://deb.nodesource.com/setup_14.x | sudo -E bash -
sudo apt-get install -y nodejs


sudo cp /${boot_dir}/nodeserver_nginx.conf /etc/nginx/sites-available/
sudo rm /etc/nginx/sites-enabled/default

sudo ln -s /etc/nginx/sites-available/nodeserver_nginx.conf /etc/nginx/sites-enabled/nodeserver_nginx.conf


sudo systemctl enable nginx
sudo systemctl start nginx


sudo npm config set registry http://registry.npmjs.org/


if [[ $USER != "vagrant" ]]; then
    sudo rm -r ${web_dir}
    sudo mkdir -p ${web_dir}
    sudo cp -rT /${root_dir}/www ${web_dir}
    sudo chmod -R 775 ${web_dir}
    sudo chown -R :$USER ${web_dir}
fi
cd ${web_dir}


npm install

sudo npm install --save -g supervisor
sudo npm install -g grunt-cli
sudo npm install -g bower

sudo ln -s /usr/bin/supervisor /usr/local/bin/supervisor


# copy conf files over
cd ${boot_dir}



# systemd
sudo touch /var/log/nodeserver.sys.log
sudo chmod 666 /var/log/nodeserver.sys.log

sudo cp nodeserver.service nodeserver.service.active
sudo sed -i "s#WEB_DIR#$web_dir#g" nodeserver.service.active
sudo cp nodeserver.service.active /lib/systemd/system/nodeserver.service
sudo chmod 777 /lib/systemd/system/nodeserver.service

# start the node server daemon
sudo systemctl enable nodeserver
sudo systemctl start nodeserver


sudo cp nodeserver_monit.conf /etc/monit/conf.d/
sudo chmod 700 /etc/monit/conf.d/nodeserver_monit.conf


# start monit for error checking
sudo monit -d 10 -c /etc/monit/conf.d/nodeserver_monit.conf


cd ${web_dir}/public_src/libs
bower install

cd ${web_dir}
grunt build

sudo service nginx reload


