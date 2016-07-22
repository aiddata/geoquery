angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory) {

  $scope.$on('$viewContentLoaded', function(event) {
    d3.select("#map").classed('overlay', true);
    mapFactory.provision();

    $timeout(function() { mapFactory.refreshSize(); });
  });

});
