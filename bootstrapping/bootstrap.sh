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


boot_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
root_dir="$( dirname ${boot_dir} )"
web_dir=/var/www/query

sudo apt-get install -y unzip curl vim git nginx python-software-properties python g++ make nodejs npm upstart monit

sudo ln -s "$(which nodejs)" /usr/bin/node

sudo cp /${root_dir}/bootstrapping/nodeserver_nginx.conf /etc/nginx/sites-available/
sudo rm /etc/nginx/sites-enabled/default

sudo ln -s /etc/nginx/sites-available/nodeserver_nginx.conf /etc/nginx/sites-enabled/nodeserver_nginx.conf

###
# sudo service nginx start
# sudo service nginx reload

sudo systemctl enable nginx
sudo systemctl start nginx
###

sudo npm config set registry http://registry.npmjs.org/

sudo rm -r ${web_dir}/*
sudo mkdir -p ${web_dir}
sudo chown -R $USER: ${web_dir}
cp -rT /${root_dir}/www ${web_dir}
cd ${web_dir}

sudo npm install
sudo npm install --save -g supervisor

sudo npm install -g grunt-cli
sudo npm install -g bower

cd /${root_dir}/bootstrapping


# copy conf files over

###

# # upstart
# sudo cp nodeserver.conf nodeserver.conf.active
# sudo sed -i "s#WEB_DIR#$web_dir#g" nodeserver.conf.active
# sudo cp nodeserver.conf.active /etc/init/nodeserver.conf
# sudo chmod 777 /etc/init/nodeserver.conf
# sudo rm nodeserver.conf.active

# # start the node server daemon
# sudo start nodeserver


# systemd
sudo touch /var/log/nodeserver.sys.log
sudo chmod 666 /var/log/nodeserver.sys.log
sudo cp nodeserver.service /lib/systemd/system/nodeserver.service
sudo chmod 777 /lib/systemd/system/nodeserver.service

# start the node server daemon
sudo systemctl enable nodeserver
sudo systemctl start nodeserver

###

sudo cp nodeserver_monit.conf /etc/monit/conf.d/
sudo chmod 700 /etc/monit/conf.d/nodeserver_monit.conf


# start monit for error checking
sudo monit -d 10 -c /etc/monit/conf.d/nodeserver_monit.conf
