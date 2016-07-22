var rp = require('request-promise');
var _ = require('lodash');

var sendRequest = function (call, data) {
  var form = data || {};
  form.call = call;

  return rp({
    // uri: "http://devlabs.aiddata.wm.edu/DET/search.php",
    uri: "http://labs.aiddata.wm.edu/DET/search.php",
    method: 'POST',
    json: true,
    form: form
  });
};


module.exports.boundaries = function(req, res) {
  return sendRequest('get_boundaries')
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
  filterData.group = req.body.boundaryId;
  filterData.filters = _.omit(req.body, ['boundaryId', 'dataset']);

  return sendRequest('get_filter_count', { filter: filterData })
    .then(function(response) { res.send(response.data); })
    .catch(function(err) { res.status(500).send(err); });
};
