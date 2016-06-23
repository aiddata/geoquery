var apiModel = require('../models/api_model');

module.exports.controller = function(httpApp){
  httpApp.get('/api/boundaries', apiModel.boundaries);
  httpApp.get('/api/geometry/:geomId', apiModel.geometry);
  httpApp.get('/api/datasets/:boundaryId', apiModel.datasets);
  httpApp.post('/api/filters', apiModel.filters);
};
