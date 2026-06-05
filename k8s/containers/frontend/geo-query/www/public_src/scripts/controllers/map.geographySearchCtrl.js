angular.module('aiddataDET')
.controller('GeographySearchCtrl', function($scope, $rootScope, $timeout, $log, $state, mapFactory, boundaries) {
  $scope.boundaries = [];
  $scope.subBoundaries = [];
  $scope.formData = {};
  $scope.showFeaturedSearches = true;

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
    if (!item.subBoundaries) {
      $scope.formData.subboundary = item.name;
      $scope.formData.boundary = _.find($scope.boundaries, { boundaryId: item.options.group });
      return;
    }
    $scope.subBoundaries = _.cloneDeep(item.subBoundaries);
    $scope.formData.subboundary = $scope.formData.subboundary || $scope.subBoundaries[0].name;
  };

  $scope.selectFromFeatured = function(item) {
    $scope.formData.searchText = item.name || item.title;
  };

  $scope.$watch('formData.subboundary', function (newValue) {
    if (!newValue) {
      mapFactory.resetView();
      mapFactory.clearBoundaries();
      return;
    }
    mapFactory.mapBoundary(newValue);
  });

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.boundaries = _.each(boundaries, function(boundary) {
      boundary.tags = _.chain(boundary)
          .get('subBoundaries')
          .map(function(sub) {
            sub.tags = _.get(sub, 'extras.tags').toString();
            sub.search = sub.title + ' ' + sub.tags;
            return sub.tags;
          })
          .flatten().uniq().toString().value();
      boundary.search = boundary.name + ' ' + boundary.tags;
    });

    $scope.featuredBoundaries = _.filter($scope.boundaries, function(b) {
      return b.subBoundaries &&
             b.search.indexOf('featured') >= 0;
    });

  });

});
