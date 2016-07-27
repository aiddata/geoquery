angular.module('aiddataDET')
.controller('PlainTextQueryCtrl', function($scope, $rootScope, $log, queryFactory) {
  // $scope.dataset = '';
  // $scope.geography = '';
  // $scope.filters = [];
  // $scope.options = [];
  // $scope.editable = bool;

  function updateQueryStructure () {
    var q = [
      { value: [$scope.dataset.title] || [], pre: 'Extract data from ', optional: false },
      { value: [$scope.geography] || [], pre: 'within ', optional: false }
    ];

    if ($scope.dataset.type === 'raster') {
      q.push(
        { value: _.get($scope.options, 'options.extract_types') || [], pre: 'calculating', optional: true, key: 'options.extract_types' },
        { value: _.get($scope.options, 'files') || [], pre: 'using', optional: true, key: 'files' }
      );

    } else {
      _.each($scope.filters, function(filterValue, filterId) {
        console.log($scope.filters[filterId]);
        /* TODO: Stop storing dataset as filter */
        if (filterId !== 'dataset') {
          var filterObj = {
            value: $scope.dataset.fields[filterId].filter_type === 'slider' && !_.isEqual($scope.filters[filterId], ['All']) ?
              [_.floor(_.min($scope.filters[filterId]).toString()) + ' - ' + _.ceil(_.max($scope.filters[filterId]).toString())] :
              _.filter($scope.filters[filterId], function(d) { return d !== 'All'; }),
            pre: $scope.dataset.fields[filterId].display + ' = ',
            optional: true,
            key: filterId
          };

          if (filterObj.value.length >= 1) { q.push(filterObj); }
        }
      });
    }
    return _.filter(q, function(option) { return option.value.length >= 1; });
  }

  $scope.removeFilter = function(filter, option) {
    return $scope.dataset.type === 'release' ? queryFactory.toggleFilterOff(filter, option) :
      queryFactory.toggleOptionOff(filter, option);
  };

  function init () {
    $scope.queryStructure = updateQueryStructure();

    if ($scope.editable) {
      $scope.$watch('filters', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);

      $scope.$watch('options', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);

      $scope.$watch('dataset', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);
    }
  }
  init();

});
