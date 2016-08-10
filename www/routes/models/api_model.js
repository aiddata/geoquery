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

module.exports.requestLookup = function (req, res) {
  var searchType = req.body.search_type;
  var searchVal = req.body.search_val;

  if (!searchType || !searchVal) {
    return res.status(400).send({ message: 'Must provide a search value and search type' });
  }

  return sendRequest('get_requests', {
    search_type: searchType,
    search_val: searchVal
  })
  .then(function(response) { res.send(response.data); })
  .catch(function(err) { res.status(500).send(err); });
};

module.exports.submitRequest = function (req, res) {
  var query = req.body.query;

  return sendRequest('add_request', { request: query })
  .then(function(response) { res.send(response.data); })
  .catch(function(err) { res.status(500).send(err); });
};

module.exports.language = function (req, res) {
  var mockLanguage = {
    "help": [
      { "question": "What was the first toy advertised on television?", "answer": "Mr. Potato Head" },
      { "question": "The beaver is the national emblem of which country?", "answer": "Canada" },
      { "question": "How is the groundnut better known?", "answer": "The peanut." }
    ],
    "welcome": {
      "title": "Welcome to the Data Extraction Tool by AidData!",
      "content": "Some explanatory text!!!"
    },
    "terms_and_conditions": {
      "content": [
        "Marfa slow-carb narwhal, lumbersexual blue bottle pop-up pour-over 90's master cleanse 8-bit organic ugh blog lomo. Sriracha typewriter try-hard intelligentsia, ramps skateboard kickstarter. Tilde kinfolk humblebrag cray crucifix, taxidermy 8-bit vice typewriter blog marfa swag brunch. VHS kale chips crucifix cred williamsburg, ethical fixie try-hard raw denim direct trade. Pitchfork fashion axe vinyl affogato. Offal disrupt man bun small batch. Fingerstache flexitarian DIY mlkshk, wolf meggings meditation.",
        "Four dollar toast tattooed 3 wolf moon small batch sriracha biodiesel, tote bag beard gochujang fingerstache yr fashion axe kickstarter lo-fi. Crucifix tote bag four dollar toast, hoodie photo booth williamsburg schlitz selfies chillwave paleo fap cold-pressed authentic PBR&B. Direct trade swag normcore, salvia sartorial biodiesel farm-to-table 90's post-ironic schlitz paleo ramps ugh squid. Fingerstache craft beer dreamcatcher blog you probably haven't heard of them. Narwhal shoreditch stumptown disrupt. Flannel tilde lumbersexual before they sold out, VHS typewriter migas YOLO freegan fixie +1 flexitarian tofu 90's. Tofu celiac craft beer YOLO."
      ]
    }
  };
  return res.send(mockLanguage);
};

module.exports.featured = function (req, res) {
  var mockFeatured = { dataset_tags: ["aiddata", "geocoded", "release", "precipitation", "UDel", "temperature", "nasa", "srtm", "dem", "slope", "cgiar", "csi", "elevation", "population", "density", "ciesin", "count"] };
  return res.send(mockFeatured);
};
