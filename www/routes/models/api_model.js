var rp = require('request-promise');
var _ = require('lodash');

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
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.geometry = function (req, res) {
  var geomId = req.params.geomId;

  return sendRequest('get_boundary_geojson', { name: geomId })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.datasets = function (req, res) {
  var boundaryId = req.params.boundaryId;

  return sendRequest('get_relevant_datasets', { group: boundaryId })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.filters = function (req, res) {
  if (!req.body.dataset) {
    return res.status(400).send({ message: 'Must provide a dataset' });
  }

  var filterData = {};

  filterData.dataset = req.body.dataset;
  filterData.filters = _.chain(['ad_sector_names', 'donors', 'years'])
    .mapKeys()
    .mapValues(function(key) { return req.body[key] || ['All']; })
    .value();

  return sendRequest('get_filter_count', { filter: filterData })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};
