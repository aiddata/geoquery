angular.module('aiddataDET')
.controller('ZoomControlsCtrl', function($scope, $rootScope, $log, mapFactory) {

  $scope.options = [
    { icon: 'globe', action: mapFactory.resetView, text: 'reset map view' },
    { icon: 'plus', action: mapFactory.zoomIn, text: 'zoom in' },
    { icon: 'minus', action: mapFactory.zoomOut, text: 'zoom out' }
  ];

});
