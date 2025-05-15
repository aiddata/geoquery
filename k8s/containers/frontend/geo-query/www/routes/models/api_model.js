var rp = require('request-promise');
var _ = require('lodash');

var sendRequest = function (call, data) {
  var form = data || {};
  form.call = call;

  return rp({
    // uri: "http://devlabs.aiddata.wm.edu/DET/search.php",
    uri: "https://geo.aiddata.org/post/geoquery.php",
    method: 'POST',
    json: true,
    form: form
  });
};

module.exports.boundaries = function(req, res) {

  return sendRequest('get_boundaries', { domain: req.body.domain })
    .then(function(response) {
      if (!_.size(response.data)) {
        return res.status(500).send({ message: 'no boundaries found' });
      }

      var boundaries = _.map(response.data, function(value, key) {

        var groupTitle = _.chain(value)
          .find(function(d) { return _.has(d, 'options.group_title'); })
          .get('options.group_title')
          .value();

        return {
          name: groupTitle || key,
          boundaryId: key,
          subBoundaries: _.sortBy(value, 'name')
        };

      });

      res.send({ boundaries: boundaries });
    })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.geometry = function (req, res) {
  var geomId = req.params.geomId;

  return sendRequest('get_boundary_geojson', { name: geomId, domain: req.body.domain })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.datasets = function (req, res) {
  var boundaryId = req.params.boundaryId;

  return sendRequest('get_relevant_datasets', { group: boundaryId, domain: req.body.domain })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.filters = function (req, res) {
  if (!req.body.dataset) {
    return res.status(400).send({ message: 'Must provide a dataset' });
  }

  var filterData = {};

  filterData.dataset = req.body.dataset;
  filterData.group = req.body.boundaryId;
  filterData.filters = _.omit(req.body, ['boundaryId', 'dataset', 'domain']);

  return sendRequest('get_filter_count', { filter: filterData, domain: req.body.domain })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};

module.exports.requestLookup = function (req, res) {
  var searchType = req.body.search_type;
  var searchVal = req.body.search_val;

  if (!searchType || !searchVal) {
    return res.status(400).send({ message: 'Must provide a search value and search type' });
  }

  return sendRequest('get_requests', {
    search_type: searchType,
    search_val: searchVal,
    domain: req.body.domain
  })
  .then(function(response) { res.send(response.data); })
  .catch(function(err) { res.status(500).send(err); });
};

module.exports.submitRequest = function (req, res) {
  var query = req.body.query;

  return sendRequest('add_request', { request: query, domain: req.body.domain })
  .then(function(response) { res.send(response.data); })
  .catch(function(err) { res.status(500).send(err); });
};

module.exports.info = function (req, res) {
  return sendRequest('get_info', { domain: req.body.domain })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};
