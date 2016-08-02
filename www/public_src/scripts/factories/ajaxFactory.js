angular.module('aiddataDET')
  .factory('ajaxFactory', function($http) {

    return {

      boundaries: function () {
        return $http.get('/api/boundaries');
      },

      geometry: function (geomId) {
        return $http.get('/api/geometry/' + geomId );
      },

      datasets: function (boundaryId) {
        return $http.get('/api/datasets/' + boundaryId );
      },

      filters: function (filterData, boundaryId) {
        var data = _.extend(_.cloneDeep(filterData), { boundaryId: boundaryId });
        return $http.post('/api/filters', data);
      },

      requests: function (email) {
        return $http.post('/api/requests', { search_type: 'email', search_val: email });
      },

      submitRequest: function (query) {
        return $http.post('/api/submit', { query: query });
      }
    };
  });
