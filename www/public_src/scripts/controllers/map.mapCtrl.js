angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory) {

  function init () {
    mapFactory.provision();
    $timeout(function() {
      mapFactory.refreshSize();
    });
  }
  init();

});
