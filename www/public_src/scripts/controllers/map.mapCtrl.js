angular.module('aiddataDET')
.controller('MapCtrl', function($scope, mapFactory) {

  function init () { mapFactory.provision(); }
  init();

});
