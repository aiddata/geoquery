angular.module('aiddataDET')
.controller('GeographySearchCtrl', function($log, $scope, $state, ajaxFactory, mapFactory, queryFactory) {
  $scope.boundaries = [];
  $scope.subBoundaries = [];
  $scope.formData = {};

  $scope.defineBoundary = function() {
    $state.go('search', {
      boundary: getSelectedBoundary().boundaryId,
      subboundary: $scope.formData.subboundary
    });
  };

  $scope.$watch('formData.boundary', function (newValue) {
    if (!newValue) {
      $scope.subBoundaries.splice(0);
      $scope.formData.boundary = undefined;
      $scope.formData.subboundary = undefined;
      return;
    }

    $scope.subBoundaries = _.get(getSelectedBoundary(), 'subBoundaries');
    $scope.formData.subboundary = $scope.subBoundaries[0].name;
  });

  $scope.$watch('formData.subboundary', function (newValue) {
    if (!newValue) {
      mapFactory.resetView();
      mapFactory.clearBoundaries();
      return;
    }
    mapFactory.mapBoundary(newValue);
  });

  function getSelectedBoundary () {
    var selected = _.get($scope.formData, 'boundary.title') ||
                   _.get($scope.formData, 'boundary.originalObject');
    return _.find($scope.boundaries, { name: selected });
  }

  function init () {
    queryFactory.getBoundaries()
      .then(function(boundaries) {
        $scope.boundaries = boundaries;
      }, function (err){
        $log.error(err);
      });
  }

  init();

});
