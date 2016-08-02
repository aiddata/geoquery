angular.module('aiddataDET')
.controller('RangeCtrl', function($scope, $rootScope, $log, queryFactory) {
  // $scope.filterData
  // $scope.filterOptions
  // $scope.activeFilters

  var min = _.floor(_.min($scope.filterOptions)),
      max = _.ceil(_.max($scope.filterOptions));

  $scope.sliderOptions = {
    floor: min,
    ceil: max,
    onEnd: function() { $scope.updateRange(); }
  };

  $scope.range = { min: min, max: max };

  $scope.fields = [
    {
      text: 'min',
      validate: function (val) {
        $scope.range.min = val >= $scope.range.max ? $scope.range.max - 1 :
          val < $scope.sliderOptions.floor ? $scope.sliderOptions.floor : val;
        $scope.updateRange();
      }
    },
    {
      text: 'max',
      validate: function (val) {
        $scope.range.max = val <= $scope.range.min ? $scope.range.min + 1 :
          val > $scope.sliderOptions.ceil ? $scope.sliderOptions.ceil : val;
        $scope.updateRange();
      }
    }
  ];

  $scope.updateRange = function () {
    if (
      $scope.range.min === $scope.sliderOptions.floor &&
      $scope.range.max === $scope.sliderOptions.ceil
    ) {
      queryFactory.resetFilterRange($scope.filterData.field);
    } else {
      queryFactory.updateFilterRange($scope.range.min, $scope.range.max, $scope.filterData.field);
    }
  };

  $rootScope.$on('filters:resetRange', function(event, data) {
    if (data.filterId === $scope.filterData.field) {
      $scope.range.min = $scope.sliderOptions.floor;
      $scope.range.max = $scope.sliderOptions.ceil;
    }
  });

});
