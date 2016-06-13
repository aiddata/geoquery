var rp = require('request-promise');

var sendRequest = function (call, data) {
  var form = data || {};
  form.call = call;

  return rp({
    uri: "http://devlabs.aiddata.wm.edu/DET/search.php",
    method: 'POST',
    json: true,
    form: form
  });
};


module.exports.boundaries = function(req, res) {
  return sendRequest('get_boundaries')
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.send(err); });
};
