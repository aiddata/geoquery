angular.module('aiddataDET')
.controller('GeographySearchCtrl', function($scope, ajaxFactory) {
  $scope.boundaries = { };
  $scope.boundaryOptions = [ ];
  $scope.selectedBoundary = { };
  $scope.subBoundaries = [ ];
  $scope.selectedSubBoundary = { };

  $scope.$watch('selectedBoundary', function (newValue) {
    if (!newValue) {
      $scope.subBoundaries.splice(0);
      return;
    }
    var selection = newValue.title || newValue.originalObject;
    $scope.subBoundaries = _.cloneDeep($scope.boundaries[selection]);
    $scope.selectedSubBoundary = 0;
  });

  $scope.getBoundary = function () {
    console.log('fooo');
  };

  function init () {
    ajaxFactory.boundaries()
    .then(function(result) {
      $scope.boundaries = result.data;
      $scope.boundaryOptions = _.chain($scope.boundaries)
          .keys()
          .map(function(d) { return { name: d }; })
          .value();
    });
  }

  init();

});
