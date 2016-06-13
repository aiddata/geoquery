angular.module('wwwApp')
  .factory('ajaxFactory', function($http) {

    return {
      getAppTitle : function() {
        return $http.get('/api/getData/title')
          .then(function(result){
              return result.data;
          });
      },

      foo: function () {
        return $http.get('/api/test')
          .then(function(result){
            console.debug(result)
              return result.data;
          });
      }
    }
  });
