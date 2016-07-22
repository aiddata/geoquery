angular.module('aiddataDET')
.controller('GeographySearchCtrl', function($scope, $rootScope, $log, $state, mapFactory, boundaries) {
  $scope.boundaries = boundaries;
  $scope.subBoundaries = [];
  $scope.formData = {};
  $scope.showFeaturedSearches = false;

  $scope.defineBoundary = function() {
    $state.go('search', {
      boundary: $scope.formData.boundary.boundaryId,
      subboundary: $scope.formData.subboundary
    });
  };

  $scope.selectedItemChange = function (item) {
    if (!item) {
      $scope.subBoundaries.splice(0);
      $scope.formData.boundary = undefined;
      $scope.formData.subboundary = undefined;
      return;
    }

    $scope.subBoundaries = _.cloneDeep(item.subBoundaries);
    $scope.formData.subboundary = $scope.subBoundaries[0].name;
  };

  $scope.selectFromFeatured = function(boundaryName) {
    $scope.formData.searchText = boundaryName;
    $scope.showFeaturedSearches = false;
  };

  $scope.$watch('formData.subboundary', function (newValue) {
    if (!newValue) {
      mapFactory.resetView();
      mapFactory.clearBoundaries();
      return;
    }
    mapFactory.mapBoundary(newValue);
  });

});
