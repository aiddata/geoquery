
ubuntu_version=$(lsb_release -sr)
echo Running Ubuntu ${ubuntu_version}


boot_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
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


sudo add-apt-repository -y ppa:chris-lea/node.js
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
  # upstart - runs webserver perpetually, after restarts
  # monit - for restarting webserver after crashes, and reporting


sudo apt-get install -y unzip curl vim git nginx python-software-properties python g++ make nodejs upstart monit npm

sudo ln -s "$(which nodejs)" /usr/bin/node

sudo cp /${boot_dir}/nodeserver_nginx.conf /etc/nginx/sites-available/
sudo rm /etc/nginx/sites-enabled/default

sudo ln -s /etc/nginx/sites-available/nodeserver_nginx.conf /etc/nginx/sites-enabled/nodeserver_nginx.conf


if [[ $ubuntu_version == "14.04" ]]; then

    sudo service nginx start
    sudo service nginx reload

elif [[ $ubuntu_version == "16.04" ]]; then

    sudo systemctl enable nginx
    sudo systemctl start nginx

fi


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


# copy conf files over
cd ${boot_dir}


if [[ $ubuntu_version == "14.04" ]]; then

    # upstart
    sudo cp nodeserver.conf nodeserver.conf.active
    sudo sed -i "s#WEB_DIR#$web_dir#g" nodeserver.conf.active
    sudo cp nodeserver.conf.active /etc/init/nodeserver.conf
    sudo chmod 777 /etc/init/nodeserver.conf
    sudo rm nodeserver.conf.active

    # start the node server daemon
    sudo start nodeserver

elif [[ $ubuntu_version == "16.04" ]]; then

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

fi


sudo cp nodeserver_monit.conf /etc/monit/conf.d/
sudo chmod 700 /etc/monit/conf.d/nodeserver_monit.conf


# start monit for error checking
sudo monit -d 10 -c /etc/monit/conf.d/nodeserver_monit.conf




cd ${web_dir}/public_src/libs
bower install

cd ${web_dir}
grunt build

sudo service nginx reload


