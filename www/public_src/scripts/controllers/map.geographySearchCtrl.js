angular.module('aiddataDET')
.controller('GeographySearchCtrl', function($scope, ajaxFactory, mapFactory) {
  $scope.boundaries = [];
  $scope.subBoundaries = [ ];
  $scope.formData = {};

  $scope.$watch('formData.boundary', function (newValue) {
    if (!newValue) {
      $scope.subBoundaries.splice(0);
      $scope.formData.boundary = undefined;
      $scope.formData.subboundary = undefined;
      return;
    }

    var selection = newValue.title || newValue.originalObject;
    $scope.subBoundaries = _.chain($scope.boundaries)
      .find({ name: selection })
      .get('data')
      .cloneDeep()
      .value();
  });

  $scope.$watch('formData.subboundary', function (newValue) {
    if (!newValue) {
      mapFactory.resetView();
      mapFactory.clearBoundaries();
      return;
    }
    mapFactory.mapBoundary(newValue);
  });

  $scope.test = function () {
    console.log($scope.formData);
  };

  function init () {
    ajaxFactory.boundaries()
      .then(function(result) {
        $scope.boundaries = _.map(result.data, function(value, key) {
          return { name: key, data: value };
        });
      }, function(err) {
        console.error(err);
      });
  }

  init();

});
