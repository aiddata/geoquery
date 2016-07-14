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
        return $http.get('/api/datasets/' + boundaryId )
          .then(function(results) {
            console.log(results);
            return results;
          });
      },

      filters: function (filterData) {
        return $http.post('/api/filters', filterData);
      }
    };
  });
