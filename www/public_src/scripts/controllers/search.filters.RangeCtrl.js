angular.module('aiddataDET')
.controller('RangeCtrl', function($scope, $rootScope, $log, queryFactory) {
  // $scope.filterData
  // $scope.filterOptions
  // $scope.activeFilters

  $scope.range = {
    min: _.floor(_.min($scope.filterOptions)),
    max: _.ceil(_.max($scope.filterOptions))
  };

  $scope.sliderOptions = {
    floor: _.floor(_.min($scope.filterOptions)),
    ceil: _.ceil(_.max($scope.filterOptions)),
    onEnd: function() { $scope.updateRange(); }
  };

  $scope.fields = [
    {
      text: 'min',
      validate: function (val) {
        $scope.range.min = val >= $scope.range.max ? $scope.range.max - 1 :
          val < _.floor(_.min($scope.filterOptions)) ? _.floor(_.min($scope.filterOptions)) : val;
        $scope.updateRange();
      }
    },
    {
      text: 'max',
      validate: function (val) {
        $scope.range.max = val <= $scope.range.min ? $scope.range.min + 1 :
          val > _.ceil(_.max($scope.filterOptions)) ? _.ceil(_.max($scope.filterOptions)) : val;
        $scope.updateRange();
      }
    }
  ];

  $scope.updateRange = function () {
    console.log($scope.range);
    if ($scope.range.min === $scope.sliderOptions.floor &&
      $scope.range.max === $scope.sliderOptions.ceil) {
      return queryFactory.resetFilterRange($scope.filterData.field);
    }
    queryFactory.updateFilterRange($scope.range.min, $scope.range.max, $scope.filterData.field);
  };


  $scope.$watch('filterOptions', function(newValue, oldValue) {
    if (!oldValue) {
      var min = _.floor(_.min($scope.filterOptions)),
          max = _.ceil(_.max($scope.filterOptions));

      $scope.sliderOptions = {
        floor: min,
        ceil: max,
        stepsArray: getTicks(min, max),
        onEnd: function() { $scope.updateRange(); }
      };

      $scope.range = { min: min, max: _.last($scope.sliderOptions.stepsArray) };
    }
  });

  function getTicks (min, max) {
    var scale = d3.scaleLinear().domain([0, max]);
    var ticks = scale.ticks();
    ticks.push(_.last(ticks) + ticks[1]);
    return ticks;
  }

});
