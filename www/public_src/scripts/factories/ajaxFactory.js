angular.module('aiddataDET')
  .factory('ajaxFactory', function($http) {

    return {

      boundaries: function () {
        return $http.get('/api/boundaries');
      }

      geometry: function (geomId) {
        return $http.get('/api/geometry/' + geomId );
      }
    };
  });
