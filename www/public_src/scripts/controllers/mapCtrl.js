angular.module('aiddataDET')
.controller('MapCtrl', function($scope, mapFactory) {
  mapFactory.provision();

  $scope.refreshMapSize = mapFactory.refreshSize;
});
