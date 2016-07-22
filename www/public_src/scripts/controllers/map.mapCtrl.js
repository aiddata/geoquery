angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory) {

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision();

    $timeout(function() { mapFactory.refreshSize(); });
  });

});
