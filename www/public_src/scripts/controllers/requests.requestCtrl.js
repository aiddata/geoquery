angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $q, $state, $timeout, mapFactory, requests) {
  $scope.requests = requests;
  function makeMaps () {
    var maps = _.map(requests, function(req) {
      var el = document.querySelector('#map-' + _.get(req, '_id.$id'));
      return mapFactory.provision(el, true)
        .promise.then(function(map) {
          MAP = map;
          mapFactory.mapBoundary(req.boundary.name);
        });
    });
  }


  $scope.$on('$viewContentLoaded', function(event) {
    console.log(requests);
    $timeout(function () {
      makeMaps ();
    });

  });
});
