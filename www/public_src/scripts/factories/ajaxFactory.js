angular.module('aiddataDET')
  .factory('ajaxFactory', function($http) {

    return {

      boundaries: function () {
        return $http.get('/api/boundaries')
          .then(function(result){
            console.debug(result);
            return result.data;
          });
      }
    };
  });
