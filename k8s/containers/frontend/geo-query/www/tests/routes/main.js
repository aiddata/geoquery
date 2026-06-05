var test = require('tape'),
testServer = require('express')(),
http = require('http'),
fs = require('fs');

/*******************************************************************************
*
*   Start up test server and check to make sure the code is all valid:
*
*******************************************************************************/

testServer.set('port', 73575);

// include all controllers - taken straight from regular server setup
fs.readdirSync(__dirname + '/../../routes/controllers/').forEach(function (file) {
  if(file.substr(-3) == '.js') {
    route = require(__dirname + '/../../routes/controllers/' + file);
    route.controller(testServer);
  }
});

var server = http.createServer(testServer).listen(testServer.get('port'), function(){});

/*******************************************************************************
*
*   Make sure the server setup is all kosher
*
*******************************************************************************/


test('Everything OK, Node? Want to talk about it?', function(t){

  t.ok(server);
  t.end();

});


/*******************************************************************************
*
*   Test GET request - making sure the node server request works
*
*******************************************************************************/

test('can I GET getData/title?', function(t){

  var options = {
    host: 'localhost',
    path: '/api/getData/title',
    port: '73575',
    method: 'GET'
  };

  var req = http.request(options, function(response){
    var data = '';

    response.on('data', function(d){
      data += d;
    });

    response.on('end', function(e){
      var results = JSON.parse(data);
      t.equals(results.title, "HEY THERE");
      t.equals(results.subtitle,"welcome to your premade app!");
      t.end();

    });

  });

  req.end();

});

/*******************************************************************************
*
*   Closing the node server (doesn't need to be a test, but I figured why not)
*
*******************************************************************************/

test('Done!', function(t){

  server.close(function(){
    process.exit();
  });

  t.equals(0,0);
  t.end();

});
