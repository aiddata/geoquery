var apiModel = require('../models/api_model');

module.exports.controller = function(httpApp){
  httpApp.post('/api/boundaries', apiModel.boundaries);
  httpApp.post('/api/geometry/:geomId', apiModel.geometry);
  httpApp.post('/api/datasets/:boundaryId', apiModel.datasets);
  httpApp.post('/api/info', apiModel.info);
  httpApp.post('/api/filters', apiModel.filters);
  httpApp.post('/api/requests', apiModel.requestLookup);
  httpApp.post('/api/submit', apiModel.submitRequest);
};
