angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, mapFactory) {

  function init () { mapFactory.provision(); }
  init();

});
