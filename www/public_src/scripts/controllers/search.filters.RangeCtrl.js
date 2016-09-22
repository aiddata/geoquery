angular.module('aiddataDET')
.controller('RangeCtrl', function($scope, $rootScope, $log, $timeout, queryFactory) {
  // $scope.filterData
  // $scope.filterOptions
  // $scope.activeFilters

  var numberFormat = d3.format('$,');

  var min = _.min($scope.filterOptions),
      max = _.max($scope.filterOptions);

  $scope.range = { min: min, max: max };
  $scope.sliderOptions = { visible: false };

  $scope.updateRange = function () {
    if (
      $scope.range.min === $scope.sliderOptions.floor &&
      $scope.range.max === $scope.sliderOptions.ceil &&
      $scope.filterOptions.length > 1
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

  // $scope.$watch('activeFilters', function(newValue) {
  //   // Detect if min and max are the same
  //   // Reposition either min or max so that there is at
  //   // Least one value in the range
  //   if ( newValue.length === 2 && newValue[0] === newValue[1] ) {
  //
  //     var closest = _.chain($scope.filterOptions)
  //       .map(function(d, i) {
  //         return { index: i, abs: Math.abs(d - newValue[0]) };
  //       })
  //       .orderBy(['abs'], ['asc'])
  //       .head()
  //       .value();
  //
  //     var closestValue = $scope.filterOptions[closest.index];
  //
  //     if (closestValue < newValue[0]) {
  //       $scope.range.min = closestValue;
  //     }
  //
  //     if (closestValue >= newValue[0]) {
  //       $scope.range.max = closestValue;
  //     }
  //
  //     $scope.updateRange();
  //   }
  // }, true);

  $scope.$watch('filterOptions', function(newValue, oldValue) {
    var updateMin = $scope.range.min === min || newValue.length <= 1,
        updateMax = $scope.range.max === max || newValue.length <= 1;

    min = newValue.length ? _.floor(_.min(newValue)) : 0;
    max = newValue.length ? _.ceil(_.max(newValue)) : 0;

    $scope.range.min = updateMin || $scope.range.min < min ? min : $scope.range.min;
    $scope.range.max = updateMax || $scope.range.max > max ? max : $scope.range.max;

    $timeout(buildSlider, 500);
  });

  function buildSlider () {

    $scope.sliderOptions = {
      visible: true,
      floor: _.floor(min),
      ceil: _.ceil(max),
      onEnd: $scope.updateRange,
      enforceRange: true,
      translate: numberFormat,
      noSwitching: true,
      disabled: $scope.disabled
    };

    $scope.updateRange();
  }

  $rootScope.$on('filters:update-start', function() {
    $scope.disabled = true;
  });

  $rootScope.$on('filters:updated', function(event, data) {
    $scope.disabled = false;
  });

  $rootScope.$on('filters:rebuild', function() {
    $scope.sliderOptions.floor = _.floor(_.min($scope.filterData.distinct));
    $scope.sliderOptions.ceil = _.ceil(_.max($scope.filterData.distinct));
    $scope.range.min = $scope.sliderOptions.floor;
    $scope.range.max = $scope.sliderOptions.ceil;
    $scope.updateRange();
  });


});
