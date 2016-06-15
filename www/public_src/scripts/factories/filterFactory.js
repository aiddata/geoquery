angular.module('aiddataDET')
  .factory('filterFactory', function(ajaxFactory) {
    return {
      init: function (geomId) {
        console.log(geomId);
      }
    };
  });
